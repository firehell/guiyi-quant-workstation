## Purpose

Defines weekly bar planning semantics so 1w Direct targets converge on complete ISO weeks and actual-dominant weekly ownership follows the week-last trading day rank1 map.

## ADDED Requirements

### Requirement: Weekly watermark is last trading day of completed ISO week
The weekly planning watermark MUST equal the last trading day, according to TradingCalendar for the product exchange, of the latest ISO week that is already fully completed relative to the update through-day. The system MUST NOT treat an in-progress ISO week as a complete weekly publish window.

#### Scenario: In-progress week excluded from weekly watermark
- **WHEN** through-day falls inside an ISO week that still has remaining trading days after through-day
- **THEN** that ISO week is excluded from the weekly watermark and is not treated as a complete publishable week

### Requirement: Actual-dominant weekly ownership uses week-last rank1
For actual-dominant 1w, the owning contract for a completed week MUST be the MainContractMap `rank=1` contract on that week's last trading day. Weekly ownership MUST NOT be sliced solely by daily rollover windows used for lower frequencies.

#### Scenario: Rollover mid-week assigns week to final rank1
- **WHEN** rank1 changes mid-week and the week's last trading day maps to contract B
- **THEN** the actual-dominant 1w target for that completed week uses contract B

### Requirement: Weekly root-cause matrix is mandatory
Before M3 final Gate, the system MUST complete a failing-test or evidence matrix covering continuous and actual-dominant 1w across complete week, incomplete week, rollover week, listing-first week, and holiday-shortened week, inspecting planner, calendar/weekly watermark, provider request, and RQData batch layers. Fixes MUST target only the confirmed failing layer.

#### Scenario: Matrix blocks final gate until root cause classified
- **WHEN** 1w empty-batch or conflict behavior is still unclassified across the required matrix cells
- **THEN** M3 final Gate remains blocked even if other frequencies appear healthy
