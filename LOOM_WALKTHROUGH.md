# Loom walkthrough — target 5–7 minutes

Record your screen and narrate in your own words. Keep the dashboard, this repository, and a terminal ready. Use the exact behaviors below; avoid claiming the placeholder application had working monthly reports before the fix.

## Before recording

1. Start the app with `FRONTEND_PORT=3001 docker compose up --build -d` and open http://localhost:3001.
2. Open the source files for revenue caching, reservations, and authentication in your editor.
3. Have a terminal at the repository root, ready to run the backend and frontend test commands from README.md.
4. Start from the login page. Close unrelated tabs and avoid displaying personal credentials or tokens.

## 0:00–0:35 — introduce the task

“I investigated the supplied Property Revenue Dashboard, focusing on client isolation, reporting periods, and financial accuracy. I kept the existing application structure and added regression coverage around the reported failures. I also fixed runtime and login issues that prevented the dashboard from reliably using its actual data.”

## 0:35–1:35 — demonstrate client isolation

Log in as Sunset with the supplied credentials. Select Beach House Alpha, March 2024. Show **USD 2,250.00**, four bookings, and the three Sunset properties.

“Both clients own a property with the ID prop-001. Previously the Redis key contained only that ID, so a cached result from one client could be returned to another. The cache now includes the authenticated tenant and reporting period, and the backend checks ownership before reading it.”

Log out and log in as Ocean. Show **Mountain Lodge Beta**, the same `prop-001`, **USD 0.00**, and zero bookings. Refresh once. Select Lakeside Cottage and show **USD 1,776.50**. Mention that tests exercise both client request orders and warm caches.

## 1:35–2:40 — explain the monthly calculation

Log back in as Sunset. Select Beach House Alpha, March 2024, then February 2024, then March again.

“The original monthly function was a placeholder, while the dashboard requested an all-time summary. I connected the period selection to the actual query. A reservation at February 29, 23:30 UTC is already March 1 in Paris, so its 1,250 dollars belongs in March. The query converts both local period boundaries to UTC and includes the start while excluding the next period’s start.”

Point to the `AT TIME ZONE` boundary expressions in the reservation service. Select Full year 2024 and show the same seed-data total. Explain that tests cover different DST offsets in Paris and New York and the December/January rollover.

## 2:40–3:30 — explain money handling

“The database stores three decimal places. The three sample amounts 333.333, 333.333, and 333.334 add to exactly 1,000. Rounding each reservation first would lose a cent, so I sum the original amounts and round once at the end.”

Show the Decimal rounding and the API’s string amount. Explain that the frontend formats that string without float arithmetic. Mention separate currency groups and that no exchange rates are assumed. Do not claim that the original seeded total necessarily displayed 999.99; that is a regression scenario demonstrating why the rounding order matters.

## 3:30–4:25 — explain runtime and authentication fixes

“The original database pool used missing configuration fields and incompatible async session handling. Failures were caught and replaced with hardcoded revenue, masking the real problem. The app now uses its configured database and shared pool. Database failures return an error; a cache outage still reads the real database.”

“Tenant identity now comes from verified server-controlled claims, with no default client. The local challenge logins require the supplied passwords. Invalid and expired tokens are rejected. On the frontend I fixed the login response shape and made old requests unable to update a newer account or selection.”

Show one concise authentication test rather than reading the entire implementation.

## 4:25–5:40 — prove the fixes

Run:

```bash
docker compose exec -T backend env RUN_INTEGRATION_TESTS=1 python -m unittest discover -s tests -v
node --test frontend/tests/*.test.mjs
```

“The integration tests use the supplied PostgreSQL data and actual API. They cover both clients, cache order, month boundaries, rounding, separate currencies, and property authorization. Additional tests cover bad tokens, malformed cache entries, service failures, and frontend session races.”

Show the passing summary. Mention that the production frontend build and browser login, refresh, account switching, and period controls were checked as documented in the submission.

## 5:40–6:10 — close

“The README contains reproducible setup steps, the reporting assumptions, exact expected totals, and test commands. The fixes are committed to my fork, with a CI workflow to repeat the regression checks.”

End the recording. Verify the Loom link opens for a reviewer, then submit the fork link and Loom link through the employer’s requested channel. The repository link is https://github.com/oussch702/New_devs_App.
