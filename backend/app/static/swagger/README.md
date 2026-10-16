# Swagger UI (vendored)

`swagger-ui-bundle.js`, `swagger-ui.css` and `favicon-32x32.png` are unmodified files
from the npm package `swagger-ui-dist` **5.33.3** (Apache License 2.0,
https://github.com/swagger-api/swagger-ui). They are served at `/docs-assets/` so
the interactive API docs at `/docs` work on a campus LAN with no internet access.

To upgrade: `npm pack swagger-ui-dist@<version>`, extract the three files here, and
update the version above.
