# Security Policy

Please don't open public issues for security problems. Email **jamanbuilds@gmail.com** with
details and steps to reproduce; you'll get a reply within a few days.

Notes for anyone deploying this:
- The default configuration is for **local development** (trust auth on Postgres, no Redis password,
  CORS `*` on the API). Set credentials through `PG_DSN` / `REDIS_URL` and restrict CORS before exposing it.
- The API has no authentication. Put it behind a gateway or add OAuth2 before any shared deployment.
