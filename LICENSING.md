# Licensing

Calibra is **open source and local-first**, licensed under the
[Apache License 2.0](LICENSE). This page explains what that means in plain
English. The [LICENSE](LICENSE) file is the authoritative legal text; if
anything here conflicts with it, the LICENSE file wins.

## TL;DR

| You want to… | Allowed? |
|---|---|
| Use Calibra for research (labs, academic work, papers) | ✅ Yes |
| Use Calibra at a company, on your own data, in CI or production pipelines | ✅ Yes |
| Read, modify and fork the source | ✅ Yes |
| Redistribute Calibra or ship it inside your own product | ✅ Yes, keep the license and [NOTICE](NOTICE) |
| Run Calibra as a hosted service for others | ✅ Yes |

Apache 2.0 is an [OSI-approved](https://opensource.org/license/apache-2-0)
open-source license. It also includes an explicit patent grant from
contributors.

## What is covered

Everything in this repository **except the `ee/` directory** is licensed under
Apache 2.0. That is everything in the `calibra-robotics` package on PyPI: the
analyzers, integrity checks, `audit`, `review`, `watch`, `prune` and annotate
mode, dataset adapters, the prediction rubric, the CLI and the local dashboard.

## The `ee/` directory

`ee/` holds the Calibra Cloud extension (account login, cloud upload, outcome
sync and the hosted API). It is licensed separately under the terms in
[ee/LICENSE](ee/LICENSE), is not published to PyPI, and is not needed to use
Calibra. The open-source core never imports it; see
[ADR-012](docs/adr/adr-012-apache-core-boundary.md).

## Earlier versions

Calibra versions up to and including 0.11.x were released under the Business
Source License 1.1. Those releases keep their original terms, which convert to
Apache 2.0 on 2030-06-30. Upgrading to the current version gives you the
Apache 2.0 terms now.

## Commercial support

For support, custom work or the Calibra Cloud extension, contact
**omertahtaci05@gmail.com**.

## Contributions

External pull requests are not accepted yet. When they open, contributors
will sign the [Contributor License Agreement](CLA.md) before their first pull
request is merged. Contributors keep the copyright in their work.
