---
name: plan
description: Design a feature or change before any code is written. Produces the public interface, the behaviors to test, and open questions, agreed in the conversation before /feature builds it. Use when the user says "plan", "design", or "how should we add X".
argument-hint: <feature or change to design>
model: opus
effort: high
---

Plan: $ARGUMENTS

Design before building. The output is a plan `/feature` can execute from
this conversation without further design decisions.

1. Orient. Read the relevant modules under `src/algorithm_playground/` and
   their tests. Use the `scout` agent for anything beyond a few file reads.
   State what exists today in two or three sentences.
2. Interface first. Write the public signatures with full annotations and
   Google docstrings (summary, Args, Returns, Raises). The docstring is the
   contract the tests will hold the code to. Private helpers are not part of
   the plan.
3. Behaviors to test, one line each: happy paths, every documented
   `Raises:`, boundaries, empty inputs, and any invariant that suits a
   property test. This list is what the tests get written from.
4. Risks and questions: anything ambiguous in the request, any choice with a
   real alternative, any new dependency. Ask the user now rather than guess.
5. Present the plan in the conversation under the headings Context,
   Interface, Behaviors, Open questions, Out of scope. Under 150 lines.

Write no implementation and no tests here. Finish by asking for sign-off on
the open questions; `/feature` starts from the agreed plan.
