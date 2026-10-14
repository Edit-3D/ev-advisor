export type Citation = {
  url?: string;
  title?: string;
  document_filename?: string;
  section_heading?: string;
};

export type ExternalReference = {
  url: string;
  title: string;
  publisher: string;
  website: string;
};

const KNOWN_REFERENCES: Record<string, { title: string; publisher: string }> = {
  "https://www.energy.gov/articles/winterizing-your-electric-vehicle": {
    title: "Winterizing Your Electric Vehicle",
    publisher: "U.S. Department of Energy",
  },
  "https://www.energy.gov/sites/default/files/2024-10/Impact_of_Cold_Ambient_Temperature_on_BEV_Performance_v15_TechEditFinal_12Sep2024__0.pdf": {
    title: "Impact of Cold Ambient Temperature on BEV Performance",
    publisher: "U.S. Department of Energy",
  },
  "https://www.geotab.com/blog/ev-battery-health/": {
    title: "EV Battery Health",
    publisher: "Geotab",
  },
  "https://www.nrel.gov/docs/fy25osti/92113.pdf": {
    title: "NREL Report 92113",
    publisher: "National Renewable Energy Laboratory",
  },
  "https://www.fueleconomy.gov/feg/label/learn-more-electric-label.shtml": {
    title: "Electric Vehicle Fuel Economy Label",
    publisher: "FuelEconomy.gov",
  },
};

const PUBLISHERS: Array<[string, string]> = [
  ["afdc.energy.gov", "Alternative Fuels Data Center"],
  ["energy.gov", "U.S. Department of Energy"],
  ["nrel.gov", "National Renewable Energy Laboratory"],
  ["geotab.com", "Geotab"],
  ["fueleconomy.gov", "FuelEconomy.gov"],
];

function parsedExternalUrl(value?: string): URL | null {
  if (!value) return null;
  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    if (parsed.username || parsed.password) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function normalizedExternalUrl(value?: string): string | null {
  const parsed = parsedExternalUrl(value);
  if (!parsed) return null;
  parsed.hash = "";
  return parsed.href;
}

function publisherFor(parsed: URL): string {
  const hostname = parsed.hostname.toLowerCase().replace(/^www\./, "");
  return PUBLISHERS.find(([domain]) => hostname === domain || hostname.endsWith(`.${domain}`))?.[1]
    ?? hostname;
}

function readablePathLabel(parsed: URL): string {
  const segment = decodeURIComponent(parsed.pathname.split("/").filter(Boolean).at(-1) ?? "")
    .replace(/\.(?:html?|shtml|pdf)$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!segment) return publisherFor(parsed);
  return segment.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function knownReference(parsed: URL): { title: string; publisher: string } | undefined {
  const withoutFragment = new URL(parsed.href);
  withoutFragment.hash = "";
  return KNOWN_REFERENCES[withoutFragment.href]
    ?? KNOWN_REFERENCES[withoutFragment.href.replace(/\/$/, "")]
    ?? KNOWN_REFERENCES[`${withoutFragment.href}/`];
}

export function externalReferences(citations: Citation[]): ExternalReference[] {
  const seen = new Set<string>();
  const references: ExternalReference[] = [];

  for (const citation of citations) {
    const key = normalizedExternalUrl(citation.url);
    const parsed = parsedExternalUrl(citation.url);
    if (!key || !parsed || seen.has(key)) continue;
    seen.add(key);

    const known = knownReference(parsed);
    const website = parsed.pathname.toLowerCase().endsWith(".pdf")
      ? "PDF"
      : parsed.hostname.toLowerCase().replace(/^www\./, "");
    references.push({
      url: citation.url!.trim(),
      title: known?.title ?? readablePathLabel(parsed),
      publisher: known?.publisher ?? publisherFor(parsed),
      website,
    });
  }

  return references;
}
