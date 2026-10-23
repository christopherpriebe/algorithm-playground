// Hands-off counterpart of the /feature skill, for the Workflow tool.
//
//   /feature-workflow <change description>   (a path to a markdown plan also works)
//
// Models are named explicitly at every stage: opus for planning, test
// writing, and the fake-test check; the implementer and reviewer agents from
// .claude/agents/ carry their own models (sonnet and opus). Nothing inherits
// the session model. The script stops early, instead of guessing, when the
// plan has open questions or the implementer reports a blocked test.

export const meta = {
  name: 'feature-workflow',
  description: 'Build a change test-first: failing tests, implementation, adversarial review, full gate',
  whenToUse:
    'Hands-off counterpart of the /feature skill. Pass a change description (or a path to a markdown plan) as args.',
  phases: [
    { title: 'Plan', detail: 'Read the plan file or design the change', model: 'opus' },
    { title: 'Tests', detail: 'Write failing tests; a skeptic checks for fake tests', model: 'opus' },
    { title: 'Implement', detail: 'implementer makes the tests pass without touching them', model: 'sonnet' },
    { title: 'Review', detail: 'reviewer audits the diff; implementer fixes blockers', model: 'opus' },
    { title: 'Gate', detail: 'uv run nox must pass', model: 'haiku' },
  ],
}

// ---- Inputs ---------------------------------------------------------------
const REQUEST = typeof args === 'string' ? args : (args && args.task) || ''
if (!REQUEST) {
  throw new Error('feature-workflow: pass a plan path or a change description via args')
}
const MAX_ROUNDS = 2
const JUDGE = 'opus'
const RUNNER = 'haiku'

// ---- Schemas --------------------------------------------------------------
const PLAN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    slug: { type: 'string', description: 'kebab-case name for the change' },
    context: { type: 'string', description: 'What exists today, two or three sentences' },
    interface: {
      type: 'string',
      description: 'Public signatures with full annotations and Google docstrings, as Python source',
    },
    behaviors: { type: 'array', items: { type: 'string' }, description: 'One testable behavior per entry' },
    test_file: { type: 'string', description: 'Path under tests/ where the tests go' },
    open_questions: {
      type: 'array',
      items: { type: 'string' },
      description: 'Ambiguities a human must settle; empty if none',
    },
  },
  required: ['slug', 'context', 'interface', 'behaviors', 'test_file', 'open_questions'],
}

const TESTS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    coverage: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          test: { type: 'string' },
          behavior: { type: 'string' },
          failure_now: { type: 'string', description: 'The assertion or exception the test fails with today' },
        },
        required: ['test', 'behavior', 'failure_now'],
      },
    },
    untestable: { type: 'array', items: { type: 'string' } },
  },
  required: ['files', 'coverage', 'untestable'],
}

const FAKE_TEST_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    fake_tests: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { test: { type: 'string' }, reason: { type: 'string' } },
        required: ['test', 'reason'],
      },
    },
    uncovered_behaviors: { type: 'array', items: { type: 'string' } },
  },
  required: ['fake_tests', 'uncovered_behaviors'],
}

const IMPLEMENTATION_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    changed: { type: 'array', items: { type: 'string' }, description: 'path: one-line summary' },
    undone: { type: 'array', items: { type: 'string' } },
    decisions: { type: 'array', items: { type: 'string' } },
    suppressions: { type: 'array', items: { type: 'string' } },
    blocked: {
      type: 'array',
      items: { type: 'string' },
      description: 'Tests that look wrong or impossible to satisfy, with what is wrong; empty if none',
    },
    tests_pass: { type: 'boolean' },
  },
  required: ['changed', 'undone', 'decisions', 'suppressions', 'blocked', 'tests_pass'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['ship', 'revise'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          location: { type: 'string' },
          scenario: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'location', 'scenario', 'fix'],
      },
    },
    not_reviewed: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'findings', 'not_reviewed'],
}

const GATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    passed: { type: 'boolean' },
    failing_sessions: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: 'Failing output trimmed to what a fixer needs' },
  },
  required: ['passed', 'failing_sessions', 'summary'],
}

const numbered = (items) => items.map((item, i) => `${i + 1}. ${item}`).join('\n')

// ---- Plan -----------------------------------------------------------------
phase('Plan')
const isPlanFile = /\.md$/.test(REQUEST.trim())
const plan = await agent(
  isPlanFile
    ? `Read the design note at ${REQUEST.trim()} and return its content in the requested structure. Do not redesign it; a missing required section goes in open_questions.`
    : `Design this change following the steps of the /plan skill: orient (use the scout agent if needed), interface first, behaviors to test, risks. Write no implementation and no tests.\n\nCHANGE:\n${REQUEST}`,
  { label: 'plan', phase: 'Plan', model: JUDGE, schema: PLAN_SCHEMA },
)
if (!plan) throw new Error('feature-workflow: planning produced no result')
if (plan.open_questions.length) {
  log(`Stopping: ${plan.open_questions.length} open question(s) need a human.`)
  return { status: 'needs-answers', slug: plan.slug, open_questions: plan.open_questions, plan }
}
log(`Plan "${plan.slug}": ${plan.behaviors.length} behavior(s), tests in ${plan.test_file}`)

const contract = `INTERFACE (the contract):\n${plan.interface}\n\nBEHAVIORS TO COVER:\n${numbered(plan.behaviors)}`

// ---- Tests ----------------------------------------------------------------
phase('Tests')
let tests = null
let check = null
let feedback = ''
for (let round = 1; round <= MAX_ROUNDS; round++) {
  tests = await agent(
    `Write failing tests in ${plan.test_file} for every behavior below, following .claude/rules/tests.md. Edit nothing outside tests/. Each test must fail today for the right reason (an assertion or the documented exception, not an import error). Run \`uv run pytest ${plan.test_file} -n0\` and report the failure each produces, then stage the files with \`git add tests/\`.${feedback}\n\n${contract}`,
    { label: `tests:write:${round}`, phase: 'Tests', model: JUDGE, schema: TESTS_SCHEMA },
  )
  if (!tests) throw new Error('feature-workflow: test writing produced no result')
  check = await agent(
    `You are a skeptical test reviewer. Read ${tests.files.join(', ')} against the behavior list. Flag every fake test: one that asserts nothing, asserts only what a mock was told to return, mirrors an implementation instead of the contract, or cannot fail for the behavior it names. List any behavior with no test. Read-only.\n\nBEHAVIORS:\n${numbered(plan.behaviors)}`,
    { label: `tests:skeptic:${round}`, phase: 'Tests', model: JUDGE, schema: FAKE_TEST_SCHEMA },
  )
  if (!check) throw new Error('feature-workflow: the test skeptic produced no result')
  if (!check.fake_tests.length && !check.uncovered_behaviors.length) break
  log(`Round ${round}: ${check.fake_tests.length} fake test(s), ${check.uncovered_behaviors.length} uncovered behavior(s).`)
  feedback = `\n\nA reviewer rejected the previous attempt. Fix these fake tests: ${JSON.stringify(check.fake_tests)}. Add tests for: ${JSON.stringify(check.uncovered_behaviors)}.`
}
if (check && (check.fake_tests.length || check.uncovered_behaviors.length)) {
  log('Stopping: the tests still fail the skeptic after the last round; a human decides.')
  return { status: 'needs-human', slug: plan.slug, plan, tests, skeptic: check }
}

// ---- Implement ------------------------------------------------------------
phase('Implement')
const implementation = await agent(
  `Make every test in ${tests.files.join(', ')} pass without editing anything under tests/. Implement exactly the interface below; keep helpers private. Run \`uv run pytest ${plan.test_file} -n0\` until green, then \`uv run nox -s lint typecheck\`. A test that looks wrong goes in "blocked", not in your edits.\n\n${contract}`,
  { label: 'implement', phase: 'Implement', agentType: 'implementer', schema: IMPLEMENTATION_SCHEMA },
)
if (!implementation) throw new Error('feature-workflow: implementer produced no result')
if (implementation.blocked.length) {
  log(`Stopping: implementer reported ${implementation.blocked.length} blocked test(s) for a human.`)
  return { status: 'blocked', slug: plan.slug, blocked: implementation.blocked, plan, tests, implementation }
}
if (!implementation.tests_pass) {
  log('Implementer could not make the tests pass; returning its report for a human.')
  return { status: 'implementation-failed', slug: plan.slug, plan, tests, implementation }
}

// ---- Review ---------------------------------------------------------------
phase('Review')
let review = null
let mustFix = []
const fixes = []
for (let round = 1; round <= MAX_ROUNDS + 1; round++) {
  review = await agent(
    `Review the uncommitted and staged changes (\`git status --porcelain\`, \`git diff\`, \`git diff --cached\`, plus untracked files under src/ and tests/) for the change "${plan.slug}". The interface and behaviors below are the contract.\n\n${contract}`,
    { label: `review:${round}`, phase: 'Review', agentType: 'reviewer', schema: REVIEW_SCHEMA },
  )
  if (!review) throw new Error('feature-workflow: reviewer produced no result')
  mustFix = review.findings.filter((f) => f.severity !== 'minor')
  if (review.verdict === 'ship' || !mustFix.length) break
  if (round > MAX_ROUNDS) break
  log(`Review round ${round}: ${mustFix.length} blocker/major finding(s); sending to implementer.`)
  const fix = await agent(
    `Fix these review findings without editing tests/ and without changing the public interface. Re-run \`uv run pytest ${plan.test_file} -n0\` and \`uv run nox -s lint typecheck\` afterwards.\n\nFINDINGS:\n${mustFix.map((f) => `- [${f.severity}] ${f.location}: ${f.scenario}. Fix: ${f.fix}`).join('\n')}`,
    { label: `review:fix:${round}`, phase: 'Review', agentType: 'implementer', schema: IMPLEMENTATION_SCHEMA },
  )
  fixes.push(fix)
}
if (mustFix.length) {
  log(`Stopping: ${mustFix.length} blocker/major finding(s) remain after ${MAX_ROUNDS} fix round(s); a human decides.`)
  return { status: 'needs-human', slug: plan.slug, plan, tests, implementation, fixes, review }
}

// ---- Gate -----------------------------------------------------------------
phase('Gate')
let gate = null
for (let round = 1; round <= MAX_ROUNDS + 1; round++) {
  gate = await agent(
    'Run `uv run nox` and report whether every session passed. Edit nothing. If it fails, trim the output to what a fixer needs.',
    { label: `gate:${round}`, phase: 'Gate', model: RUNNER, effort: 'low', schema: GATE_SCHEMA },
  )
  if (!gate) throw new Error('feature-workflow: the gate runner produced no result')
  if (gate.passed || round > MAX_ROUNDS) break
  log(`Gate failed (${gate.failing_sessions.join(', ')}); fix attempt ${round}.`)
  const fix = await agent(
    `The full gate failed. Fix the cause without editing tests/ or weakening any check.\n\nFAILING SESSIONS: ${gate.failing_sessions.join(', ')}\n\nOUTPUT:\n${gate.summary}`,
    { label: `gate:fix:${round}`, phase: 'Gate', agentType: 'implementer', schema: IMPLEMENTATION_SCHEMA },
  )
  fixes.push(fix)
}

return {
  status: gate.passed ? 'done' : 'gate-failed',
  slug: plan.slug,
  plan,
  tests,
  implementation,
  fixes,
  review,
  gate,
}
