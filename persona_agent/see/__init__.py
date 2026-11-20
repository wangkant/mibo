"""Seeing by picture: computer use for what has no structure to read.

The two loops read structure first (the page's accessibility tree, a window's
UI Automation tree). Where that gives almost nothing (a canvas, a drawn
program, a game, a remote desktop, a window whose tree is empty), or says
something the picture contradicts, and only when the person's model takes
pictures and the person switched pictures on, the character looks at a picture
of the one granted window or the pane and works it by pointing.

- capture: a picture of the pane's page or of one granted window, scaled for
  the model, with the mapping back to real pixels (frame.Frame), password
  fields painted over before it leaves.
- profile: how each model points (0-1000 or pixels, marks, a second look).
- ask: the prompt and the strict reading of the answer.
- act: click, double click, drag, scroll, type and keys at a point through
  the pane's DevTools input or real input into the granted window, each
  followed by a second picture; the gate looks up what is at the point.
- when: whether to look by picture at all, and the person's switch.
- run: the loop of one task by sight, which either loop hands a window to.
- native: vendor computer-use tools mapped onto the same actions.
"""
