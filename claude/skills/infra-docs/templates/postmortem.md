# Postmortem: <incident summary> (<YYYY-MM-DD>)

- **Severity:** SEV1 | SEV2 | SEV3
- **Impact window:** <start> → <end> (<total duration>)
- **Author / responders:**
- **Status:** Draft | Reviewed | Actions done
- **Principle:** blameless — describe the system and the decisions, do not blame a person.

## 1. Summary

<3–5 lines: what happened, who was affected, how it was fixed.>

## 2. Impact

- Users / services:
- Data (lost / wrong / delayed):
- SLO budget used:

## 3. Timeline

| Time | Event | Source (alert / log / person) |
|---|---|---|

## 4. Root cause

<Chain of causes (5 whys). Separate the direct cause from the contributing conditions.>

## 5. Detection & response

- How was it detected, and after how long? How should it have been detected?
- What helped us fix it fast? What slowed us down?

## 6. Actions

| Action | Type (prevent / detect / reduce impact) | Owner | Due | Status |
|---|---|---|---|---|

## 7. Lessons for the AI rules (devops-ai-kit)

<If the AI was involved: which rule / skill / permission should be added or changed so this does not happen again. Name the exact file and the suggested content.>

## 8. References

- Related change record / PR:
- Dashboards / queries used in the investigation:
