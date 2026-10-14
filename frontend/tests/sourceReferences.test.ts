import assert from "node:assert/strict";
import test from "node:test";
import { externalReferences, normalizedExternalUrl } from "../src/sourceReferences.ts";

test("normalizes only safe URL equivalences", () => {
  assert.equal(
    normalizedExternalUrl(" HTTPS://ENERGY.GOV:443/articles/winterizing-your-electric-vehicle#range "),
    "https://energy.gov/articles/winterizing-your-electric-vehicle",
  );
  assert.notEqual(
    normalizedExternalUrl("https://energy.gov/article?a=1"),
    normalizedExternalUrl("https://energy.gov/article?a=2"),
  );
});

test("deduplicates identical and safely equivalent URLs in first-occurrence order", () => {
  const references = externalReferences([
    { url: "https://energy.gov/article#one", document_filename: "first.md" },
    { url: "https://ENERGY.GOV:443/article#two", document_filename: "second.md" },
    { url: "https://geotab.com/blog/ev-battery-health/", document_filename: "first.md" },
  ]);

  assert.deepEqual(references.map(({ url }) => url), [
    "https://energy.gov/article#one",
    "https://geotab.com/blog/ev-battery-health/",
  ]);
});

test("keeps distinct references from the same knowledge document", () => {
  const references = externalReferences([
    { url: "https://afdc.energy.gov/fuels/electricity-stations", document_filename: "charging.md" },
    { url: "https://afdc.energy.gov/fuels/electricity-charging-public", document_filename: "charging.md" },
  ]);
  assert.equal(references.length, 2);
});

test("uses deterministic titles and publisher fallbacks without requiring metadata", () => {
  const [known, fallback] = externalReferences([
    { url: "https://www.energy.gov/articles/winterizing-your-electric-vehicle" },
    { url: "https://docs.example.org/guides/a-very-long_ev-reference-title-for-drivers.html" },
  ]);

  assert.deepEqual(known, {
    url: "https://www.energy.gov/articles/winterizing-your-electric-vehicle",
    title: "Winterizing Your Electric Vehicle",
    publisher: "U.S. Department of Energy",
    website: "energy.gov",
  });
  assert.equal(fallback.title, "A Very Long Ev Reference Title For Drivers");
  assert.equal(fallback.publisher, "docs.example.org");
});

test("rejects missing, malformed, credentialed, and unsafe URLs", () => {
  assert.deepEqual(externalReferences([
    {},
    { url: "not a URL" },
    { url: "javascript:alert(1)" },
    { url: "https://user:secret@example.com/report" },
  ]), []);
});

test("leaves original citations and unrelated manufacturer links untouched", () => {
  const citations = [{
    url: "https://www.energy.gov/articles/winterizing-your-electric-vehicle#range",
    title: "Internal RAG document",
    document_filename: "real_world_range.md",
    section_heading: "Cold weather",
  }];
  const snapshot = structuredClone(citations);
  const answer = "[Volvo EX30](https://www.volvocars.com/se/cars/ex30-electric/)";

  externalReferences(citations);
  assert.deepEqual(citations, snapshot);
  assert.match(answer, /volvocars\.com/);
});
