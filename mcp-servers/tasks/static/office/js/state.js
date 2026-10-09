// Everything the office knows right now, in one object.
//
// One object rather than eight exported bindings, because several of these
// are REASSIGNED when a read lands (S.AGENTS = ..., S.HANDOFFS = ...) and an
// imported binding can only be reassigned by the module that declares it.
// Writing through one object sidesteps that entirely and keeps every reader
// looking at the same thing.
//
// Mutable on purpose. This is a drawing surface's working set, not a store.

export const S = {
  //: The person's own agents, as the model listing returns them.
  AGENTS: [],
  //: Whether each is working right now, and when it last ran.
  ACTIVITY: {},
  //: Runs, average, success rate and cost per agent.
  STATS: {},
  //: The skill catalogue, by name.
  SKILLS: {},
  //: Whose card the side panel is showing.
  SELECTED: null,
  //: Recent handoffs, which is the only thing a talk line may be drawn from.
  HANDOFFS: [],
  //: Where each agent is standing, in percentages of the canvas, so a talk
  //: line survives a zoom without being recomputed.
  AT: {},
  //: The tool each agent started and has not finished, for its badge.
  TOOL_NOW: {},
  //: What the team still has to do, from tasks.items.
  TODO: { open: [], done: [] },
};

export function nameOf(id) {
  const m = S.AGENTS.filter((a) => a.id === id)[0];
  return (m && m.name) || "";
}
