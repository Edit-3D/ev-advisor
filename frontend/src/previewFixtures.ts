import type { Citation, DetailsView } from "./DetailsPanel";

export type PreviewMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  agentsInvoked?: string[];
  toolsCalled?: string[];
};

export type PreviewFailure = {
  message: string;
  originalMessage: string;
  conversationId: string | null;
  stopped: boolean;
};

type MockChatResponse = {
  reply: string;
  conversation_id: string;
  citations: Citation[];
  agents_invoked: string[];
  tools_called: string[];
};

export type PreviewScenario = {
  label: string;
  messages: PreviewMessage[];
  loading?: boolean;
  failure?: PreviewFailure;
  detailsView?: DetailsView;
};

const sources: Citation[] = [
  { url: "https://www.energy.gov/articles/winterizing-your-electric-vehicle", title: "Rated and Real-World EV Range", document_filename: "real_world_range.md", section_heading: "Cold-weather efficiency" },
  { url: "https://www.energy.gov/sites/default/files/2024-10/Impact_of_Cold_Ambient_Temperature_on_BEV_Performance_v15_TechEditFinal_12Sep2024__0.pdf", title: "Rated and Real-World EV Range", document_filename: "real_world_range.md", section_heading: "Cold-weather efficiency" },
  { url: "https://www.geotab.com/blog/ev-battery-health/", title: "EV Battery Health", document_filename: "battery_health.md", section_heading: "Everyday charging" },
  { url: " https://www.energy.gov/articles/winterizing-your-electric-vehicle#preconditioning ", title: "EV Battery Health", document_filename: "battery_health.md", section_heading: "Temperature" },
];

const normalResponse: MockChatResponse = {
  reply: "Hello! I can help you compare electric vehicles, estimate charging costs, and explain EV ownership topics.",
  conversation_id: "preview-normal",
  citations: [],
  agents_invoked: [],
  tools_called: [],
};

const vehicleResponse: MockChatResponse = {
  reply: `## Volvo EX30 vs Hyundai IONIQ 5

The selected configurations emphasize different priorities:

| Configuration | Battery | Rated range | DC charging |
| --- | ---: | ---: | ---: |
| **Volvo EX30 (2025 Extended Range)** | 64 kWh | 476 km | 153 kW |
| **Hyundai IONIQ 5 (2025 Base)** | 72.6 kWh | 507 km | 220 kW |

### Practical trade-offs

- The **EX30** is more compact and easier to place in urban traffic.
- The **IONIQ 5** offers faster peak DC charging and more cabin space.
- Specifications can differ across model years and trims.

Official pages: [Volvo EX30](https://www.volvocars.com/se/cars/ex30-electric/) · [Hyundai IONIQ 5](https://www.hyundai.com/se/sv/bilar/ioniq-5.html)`,
  conversation_id: "preview-vehicle",
  citations: [],
  agents_invoked: ["vehicle"],
  tools_called: ["search_vehicles", "compare_vehicles"],
};

const researchResponse: MockChatResponse = {
  reply: `## Why cold weather reduces EV range

Cold weather affects an EV in several ways:

1. **Battery chemistry slows down**, increasing internal resistance.
2. **Cabin heating uses energy** that would otherwise move the vehicle.
3. Cold air and winter tyres can increase driving resistance.

Preconditioning while plugged in and using seat heating efficiently can reduce the impact.`,
  conversation_id: "preview-research",
  citations: [sources[0], sources[2]],
  agents_invoked: ["research"],
  tools_called: ["search_ev_knowledge"],
};

const multiAgentResponse: MockChatResponse = {
  reply: `## Winter highway recommendation

For frequent winter highway trips, the **Hyundai IONIQ 5 (2025 Base)** is the stronger fit because its higher DC charging peak and larger battery provide more flexibility on longer journeys.

| Consideration | Volvo EX30 | Hyundai IONIQ 5 |
| --- | --- | --- |
| Urban usability | Excellent | Good |
| Highway comfort | Good | **Very good** |
| Peak DC charging | 153 kW | **220 kW** |
| Winter strategy | Precondition before departure | Precondition before departure and charging |

Actual winter range depends on temperature, speed, wind, tyres, and cabin-heating use.`,
  conversation_id: "preview-multi",
  citations: sources,
  agents_invoked: ["vehicle", "research"],
  tools_called: ["compare_vehicles", "search_ev_knowledge"],
};

function conversation(userText: string, response: MockChatResponse, id: number): PreviewMessage[] {
  return [
    { id, role: "user", text: userText },
    {
      id: id + 1,
      role: "assistant",
      text: response.reply,
      citations: response.citations,
      agentsInvoked: response.agents_invoked,
      toolsCalled: response.tools_called,
    },
  ];
}

const multiMessages = conversation(
  "Compare the Volvo EX30 and Hyundai IONIQ 5 for winter highway driving.",
  multiAgentResponse,
  500,
);

export const PREVIEW_SCENARIOS = {
  welcome: { label: "Welcome screen", messages: [] },
  normal: {
    label: "Normal conversation",
    messages: conversation("Hello!", normalResponse, 100),
  },
  vehicle: {
    label: "Vehicle comparison",
    messages: conversation("Compare the Volvo EX30 and Hyundai IONIQ 5, and include official links.", vehicleResponse, 200),
  },
  research: {
    label: "Research response",
    messages: conversation("Why does cold weather reduce EV range?", researchResponse, 300),
  },
  multi: { label: "Multi-agent response", messages: multiMessages },
  sources: { label: "Sources panel", messages: multiMessages, detailsView: "sources" },
  execution: { label: "Execution Details panel", messages: multiMessages, detailsView: "execution" },
  loading: {
    label: "Loading state",
    messages: [{ id: 600, role: "user", text: "Find three Volvo EVs with at least 400 km range." }],
    loading: true,
  },
  error: {
    label: "Error and retry",
    messages: [{ id: 700, role: "user", text: "Compare two family EVs." }],
    failure: {
      message: "The AI service is temporarily unavailable. Please try again shortly.",
      originalMessage: "Compare two family EVs.",
      conversationId: "preview-error",
      stopped: false,
    },
  },
  stopped: {
    label: "Stopped generation",
    messages: [{ id: 800, role: "user", text: "Explain battery preconditioning." }],
    failure: {
      message: "Response stopped",
      originalMessage: "Explain battery preconditioning.",
      conversationId: "preview-stopped",
      stopped: true,
    },
  },
} satisfies Record<string, PreviewScenario>;

export type PreviewScenarioId = keyof typeof PREVIEW_SCENARIOS;
