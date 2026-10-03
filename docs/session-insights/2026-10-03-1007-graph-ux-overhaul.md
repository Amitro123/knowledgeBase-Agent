# Graph UX Overhaul — Session Insight

## Task / problem summary

Issue #9 requested a comprehensive UX overhaul of the graph tab in a single-file Hebrew RTL knowledge base app. The graph visualizes ~120 resources across 6 categories and 80 tags using vis-network. The core problem: opening the graph showed a dense 200-node network that was unusable for navigation.

## Root cause

The graph defaulted to showing all nodes at once (`graphViewMode = 'all'`), with no visible controls, no filtering, and no progressive disclosure. Users had no way to build a mental model of the knowledge structure before diving into a dense network.

## What went well

- All six priority items (P0 through P2) shipped in one PR
- The cluster-first default dramatically reduces initial cognitive load (~12-15 hub nodes vs ~200)
- vis-network's built-in hierarchical layout handled the hierarchy mode with minimal custom code
- The collapsible legend and graph-local filters compose well with existing card filters

## What went poorly

- First iteration of cluster mode still showed ~40-50 nodes because the hub tag threshold was too low (≥2). Raising it to ≥5 fixed it
- Hierarchy mode initially rendered horizontally because `sortMethod: 'directed'` fought against edge direction (edges go resource→category, opposite to the desired hierarchy). Switching to `hubsize` + explicit `level` properties fixed it
- `renderGraph()` called `applyGraphFilter()` before `applyHubMode()`, causing a flash of all nodes. Had to restructure the render flow to dispatch per view mode

## How it was solved

1. Added visible graph controls (zoom in/out, fit, reset, center-on-selection) as an absolutely positioned button column
2. Enhanced the existing `highlightNeighbors()` with a `getLinkReason()` function that returns Hebrew text like "תגית משותפת: RAG"
3. Replaced the simple legend with a structured, collapsible panel explaining node shapes and edge types
4. Changed default `graphViewMode` from `'all'` to `'hubs'` and raised the hub threshold
5. Added graph-local filter bar with three dropdowns (category, node type, tag) and live result count
6. Added a 3-mode layout switcher and a canvas-based minimap
7. Hierarchy mode destroys and recreates the vis-network instance (required by vis-network to switch between force-directed and hierarchical layouts)

## Tradeoffs or alternatives considered

- **Separate JS/CSS files**: Kept the single-file architecture per the repo's convention
- **vis-network vs d3 or sigma.js**: Kept vis-network since it was already in use and handles both force-directed and hierarchical layouts
- **Hub threshold 2 vs 5**: threshold 2 showed too many tags; 5 keeps cluster view clean (~12-15 nodes)
- **Hierarchy sort method**: `directed` respects edge direction but reversed the hierarchy; `hubsize` uses degree centrality which naturally places categories at top

## Tests added or updated

Manual visual testing via browser — no automated test infrastructure exists in this repo.

## Lessons learned

- vis-network's `setOptions()` cannot switch between force-directed and hierarchical layouts without destroying/recreating the network instance
- The `sortMethod: 'directed'` option can reverse a hierarchy if edges point from child to parent
- In a render flow that applies multiple visual modes, always dispatch to a single mode handler rather than chaining (filter → highlight → mode)

## Follow-up actions

- Consider adding a details side panel toggled separately from node selection (P0 item from the issue)
- Consider adding an onboarding hint overlay for first-time visitors
- Touch/pinch zoom on mobile could be tested more thoroughly
