# Investigating a deployment regression

A deployment near the start of an incident is a lead, not proof of causation.
Compare error rate and latency before and after the deployment. Check whether
affected instances run the new version and whether unchanged instances fail.

Review the release diff and configuration changes. Check dependencies for
independent failures. Request operator review before any rollback; confirm
database migration compatibility and the rollback procedure first.
