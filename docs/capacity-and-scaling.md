# Capacity and scaling model

There is no honest fixed user count without a workload definition and a load
test. A “user” can mean an authenticated account, an active browser session,
or a user generating model requests; those consume very different resources.

## Current local profile

The checked-in Compose profile is a development topology: one API container,
one PostgreSQL service, Redis, RabbitMQ/Kafka, and separate worker processes.
The default API process has a database pool of 10 plus 20 overflow connections
and a model concurrency limit of 16. The default worker processes use small
Celery concurrency values. This is useful for development and functional
testing, not a market capacity claim.

The first hard ceilings are therefore:

- model generation: approximately 16 in-flight generations per API process,
  before provider latency and rate limits are considered;
- database work: at most 30 checked-out connections per API process, shared
  with worker pools and other services;
- background work: bounded by the number and concurrency of worker replicas;
- external providers: NVIDIA/CRM/WhatsApp/email quotas can be lower than the
  application limits.

## Production sizing formula

For `N` API replicas:

```text
API database connection budget = N × (pool_size + max_overflow)
AI concurrency budget          = N × model_concurrency_per_process
```

That budget must be reconciled with the RDS connection limit, model-provider
quota, queue throughput, and p95 latency target. Worker replicas must be
counted separately because they also consume database connections.

## How to obtain a market-capacity number

Before launch, define a workload (for example, requests per active user per
minute, percentage of AI requests, upload size, and webhook rate), then run a
repeatable test against the exact image and database tier. Record the maximum
load that meets the agreed p95/p99 latency, error-rate, queue-lag, and database
connection SLOs for at least 30 minutes, followed by a recovery test.

Until that evidence exists, any number of “users supported” is only a planning
estimate and must not be used as a customer guarantee.
