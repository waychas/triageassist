# Database connection timeouts

Database timeout errors can result from an exhausted connection pool, slow
queries, a saturated database, or network failures. Timeouts alone do not
establish which explanation is correct.

Compare active connections with the configured pool limit. Check connection
wait time, database CPU, slow queries, and database reachability during the
incident window. Correlate application errors with database-side observations.

If a deployment changed pool settings, compare the configuration before and
after the release. Do not increase connection limits or restart services
without checking database capacity and obtaining operator approval.
