---
title: Light-curve pipeline
aliases: [transit pipeline]
versioned: true
versions: [v1, v2]
---
# Light-curve pipeline

The script that searches star brightness records for [[transit-method]] dips. It has versions, so a
question about it has to say which one.

| Version | Flags a candidate at |
|---|---|
| v1 | 7.1 sigma or above[^v1] |
| v2 | 7.3 sigma or above, after removing star-spot trends[^v2] |

[^v1]: raw/pipeline-log.md "Pipeline v1: transit candidates flagged at 7.1 sigma or above"
[^v2]: raw/pipeline-log.md "Pipeline v2: transit candidates flagged at 7.3 sigma or above, after removing star-spot trends"
