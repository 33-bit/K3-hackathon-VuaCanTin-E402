export const baseSlides = [
  {
    number: 1,
    eyebrow: "LEARNING SCIENCE · WEEK 04",
    title: "How memory becomes knowledge",
    subtitle: "A practical model for learning ideas that last beyond the exam.",
    type: "cover",
  },
  {
    number: 2,
    eyebrow: "THE CENTRAL QUESTION",
    title: "Why does rereading feel fluent—but fail later?",
    body: "Familiarity is not the same as recall. Recognition gives us the feeling that we know an idea, even when we cannot reconstruct it unaided.",
    note: "The test of learning is what you can bring back without the page in front of you.",
    type: "quote",
  },
  {
    number: 3,
    eyebrow: "01 · WORKING MEMORY",
    title: "Attention is a narrow workspace",
    body: "Working memory can hold only a few active ideas at once. When too many unfamiliar elements compete for attention, comprehension begins to collapse.",
    stats: [
      ["Limited", "active capacity"],
      ["Brief", "without rehearsal"],
      ["Selective", "not a full recording"],
    ],
    type: "capacity",
  },
  {
    number: 4,
    eyebrow: "02 · CHUNKING",
    title: "Group details into meaningful units",
    body: "A chunk compresses several details into one usable idea. Expertise grows as more complex patterns become available as single mental units.",
    steps: ["Notice related details", "Name the shared pattern", "Connect it to prior knowledge"],
    type: "process",
  },
  {
    number: 5,
    eyebrow: "03 · RETRIEVAL",
    title: "Practice bringing the idea back",
    body: "Retrieval is not just a test of memory—it changes memory. Each successful reconstruction makes the route to the idea easier to travel again.",
    chart: [32, 49, 63, 78, 88],
    type: "chart",
  },
  {
    number: 6,
    eyebrow: "A BETTER STUDY LOOP",
    title: "Read less. Reconstruct more.",
    body: "Study a small section, close the material, explain it from memory, then compare your explanation with the source. Use the gap as your next study target.",
    steps: ["Study", "Close", "Explain", "Check", "Repeat"],
    type: "loop",
  },
];

export const starterMessages = [
  {
    id: "welcome",
    role: "assistant",
    text: "Hi—I'm your slide tutor. Ask about a concept, select text directly from a slide, or type @ to reference a slide range.",
    suggestions: ["Summarize this deck", "Quiz me on slides 3–5", "Explain the main argument"],
  },
];

