# 2026-10-03-1812 Session Insight: Knowledge Graph Page Restyle

## Task / Problem Summary
Restyle the GitHub Pages knowledge graph page to match a reference screenshot from a different repo's graph viewer. The target layout is a full-page graph viewer with: dark navy page, compact header bar with live counts, left filter column (search, node type checkboxes with color swatches, relation checkboxes with line samples), large center graph with distinct node shapes/colors per kind and distinct edge styles, and an always-visible right details panel.

## Root Cause
The original page used a dual cards+graph view with floating overlays. It needed a ground-up CSS restructure into a 3-column CSS Grid layout. The main bug discovered during implementation was vis-network's canvas coordinate mismatch in CSS Grid: the canvas internal resolution diverged from its display size, breaking all click/hover hit detection.

## What Went Well
- The CSS restructure (header, 3-column grid, left sidebar, right panel) went smoothly
- Filter checkboxes for node types and relation types worked immediately
- Search filtering adapted cleanly from the old code
- The dark navy color scheme matched the reference well

## What Went Poorly
- vis-network's click detection was completely broken in the CSS Grid layout
- Five debugging iterations were needed to find the root cause: canvas internal height (655px) didn't match display height (978px)
- Multiple attempted fixes failed: double requestAnimationFrame, explicit pixel sizing, setSize() calls, ResizeObserver
- The actual fix required understanding that vis-network node sizes are in screen pixels, not graph units

## How It Was Solved
Two-pronged approach:
1. **Pixel ratio fix**: Force `graphNetwork.canvas.pixelRatio = 1` after creation to align canvas internal resolution with display resolution
2. **DOM-level click handler**: Bypass vis-network's built-in hit detection entirely with a custom `click` event listener on the container that:
   - Projects node graph-space positions to display pixels using `getViewPosition()` and `getScale()`
   - Measures distance from click point to projected node positions in display space
   - Compares against node sizes (which are already in display pixels)

## Tradeoffs or Alternatives Considered
- **vis-network autoResize**: Didn't fix the dimension mismatch
- **Absolute positioning for container**: Didn't help because the grid row itself was unconstrained
- **Grid row constraints (grid-template-rows: 1fr, min-height: 0)**: Fixed container size but not canvas internal resolution
- **Keeping cards view**: Removed in favor of full-page graph viewer per the reference screenshot
- **Hub/hierarchy modes**: Removed because the new node-type checkboxes provide equivalent filtering capability

## Tests Added or Updated
Manual testing via computerUse agent across 7 iterations verifying:
- 3-column layout rendering
- Node click → detail panel population
- Neighbor navigation clicks
- Node type checkbox filtering
- Relation type checkbox filtering
- Category filter dropdown
- Search text filtering

## Lessons Learned
1. **vis-network + CSS Grid**: Canvas dimension mismatches are a known class of bugs. When the canvas `width`/`height` attributes don't match `clientWidth`/`clientHeight`, all coordinate-based features break silently (clicks detect 0 nodes).
2. **Node sizes vs graph coordinates**: vis-network node `size` is in screen pixels, not graph coordinate units. Hit detection must be done in display space, not graph space.
3. **Pixel ratio**: vis-network scales canvas resolution by `window.devicePixelRatio`, but its click coordinate conversion doesn't always account for this correctly in all layout contexts.
4. **Debug via diagnostics**: `canvas.width vs canvas.clientWidth` comparison is the fastest way to diagnose vis-network coordinate issues.

## Follow-up Actions
- Consider mobile layout (currently collapses sidebars but doesn't provide alternate interaction)
- Edge style visibility could be improved at high zoom-out levels (very thin/transparent)
- The `pixelRatio = 1` fix may reduce rendering sharpness on high-DPI displays; monitor for reports
