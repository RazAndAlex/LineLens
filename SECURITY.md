# Security policy

## What LineLens is

LineLens is a single-user tool that runs on your own machine. It binds to
`127.0.0.1:8741`, which is the loopback interface, so it is not reachable from
the network. It has no accounts, no authentication, no authorization, and no
multi-tenancy. It is not production software and is not hardened.

Treat it as a desktop application that happens to use a browser for its
interface. Do not put it on a shared host, behind a reverse proxy, or on a
plant network.

## What it does with your data

The CSV you upload stays on the machine that runs LineLens. Nothing is sent
anywhere. There is no telemetry, no analytics, and no outbound call of any
kind. Uploaded data is held in memory for the life of the process.

The frontend loads no remote script, style, or font. The three typefaces are
self-hosted under `web/public/fonts/`, so a page load makes no request off the
machine. You can check this: open the browser network panel and reload. Every
request goes to `127.0.0.1`.

The app therefore works on a machine with no internet connection at all.

## Known limits

- An upload has no size cap. A large enough file can exhaust memory.
- A dataset stays in memory until the process ends. There is no eviction.
- Any local process that can reach `127.0.0.1:8741` can read any dataset
  loaded in that session. On a shared machine, do not leave it running.

## Reporting a vulnerability

Email andreialexandrurazvan@gmail.com with a description and the steps to
reproduce it. Please do not open a public issue for a security problem.

This is a portfolio project maintained by one person in their own time. Expect
a reply within a week or two, and no service-level guarantee beyond that. If a
report is valid I will fix it and credit you in the commit, unless you prefer
otherwise.

## Supported versions

The `main` branch only. There are no backports and no maintained releases.
