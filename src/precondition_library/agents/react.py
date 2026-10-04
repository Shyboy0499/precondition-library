"""Arm 1: the ReAct baseline. No library, full LLM cost per episode.

This arm is the honest yardstick the other two are measured against, so it must
be given every advantage a reasonable engineer would give it by hand: a good
system prompt, the same tool surface the compiled programs get, and the same
sandbox. A deliberately crippled baseline would make the other arms look better
and the result worthless.

The stopping rule is the part a later reader is most likely to "simplify" back
into a defect, so it is stated on `solve` as well as here: the loop stops when
the model declares the task finished -- by calling `finish`, or by a turn with no
tool call -- or when `max_steps` or `max_tool_calls` runs out. It must
**not** stop when the ground-truth checker says the environment is good. Issue
#9 names that as the flaw in an earlier sketch of this arm: a checker used as a
stopping oracle hands arm 1 information the compiled arms do not have (they run
a body once and are graded afterwards), so the baseline's success would be a
property of the oracle rather than of the agent. Nothing here imports ground
truth; the caller grades the returned transcript with the fault's own `check`.
"""

from __future__ import annotations

import json
import shlex
import subprocess

from ..program import EpisodeOutcome
from ..provider import Provider
from ..runtime.confine import run_confined
from ..runtime.guard import Verdict, screen
from ..sandbox import (
    ALLOWED_GIT_CONFIG_OVERRIDES,
    Sandbox,
    disallowed_git_config_overrides,
    run_env,
    run_git,
)
from ..signatures import TaskSignature

_GIT_TIMEOUT_S = 30.0
"""Wall-clock bound on one tool call. A git command in a local sandbox is
instant; anything slower is a hang, and hanging unattended is a failure mode."""

DEFAULT_MAX_TOOL_CALLS = 24
"""Tool calls one solve may execute, across all its turns (issue #160).

`max_steps` counts **model turns**, and a model may batch several tool calls into one:
in the first live run the agent issued 4-5 per turn, so "12 steps" meant about 45
commands in one episode and 12 in another, depending only on how the model batched.
This cap makes the budget mean the same thing for every model -- twice the turn budget,
so a model that issues one call per turn is never the one it stops."""

FINISH_TOOL = "finish"
"""The tool the model calls to declare the task done (issue #171).

The live model never ended a turn without a tool call -- it kept verifying a repository
it had already fixed until the budget ran out -- so "no tool call means done" left 3 of
5 failed build episodes failing with the checker already passing. A tool-calling model
reliably calls a tool; calling `finish` is the same declaration, made in the form the
model actually produces. It is still the agent's own verdict, never the checker's."""

NUDGE_TOOL_CALL_MARGIN = 4
"""Remaining tool calls at which the one-time budget reminder is sent (issue #171)."""

BUDGET_NUDGE = (
    "Budget check: you are about to run out of turns or tool calls. If the request is "
    "already satisfied, call `finish` now with a one-line summary. Otherwise make the "
    "one change that completes it."
)
"""Sent once, as a user message, before the turn that may be the agent's last.

Issue #171's second half. It tells the agent how much budget is left, which a human
running the agent would also see; it says nothing about whether the repository is
right, so the decision to finish stays the agent's."""

LAST_WORD = (
    "Your budget is spent: no more git commands will run. If the request is satisfied, "
    "call `finish` with a one-line summary. If it is not, reply in plain text saying what "
    "remains."
)
"""The one extra turn after a budget runs out (issue #179).

In the third live run the reminder arrived when a batching model had about one batch
left; it used that batch to make the fix, then a verification batch overran the cap,
and two repositories it had fixed ended `FAIL` with no program compiled. This turn lets
the agent say whether it is done after the cap, with `finish` the only tool on offer,
so no command can run. Only `finish` counts as done here: a plain reply means it is not.
It is the agent's own verdict, as every declaration is."""

_MAX_OUTPUT_CHARS = 4_000
"""Per-stream cap on what is fed back, so one noisy command cannot balloon the
transcript that every later turn re-sends (and is billed for)."""

_SHELL_OPERATORS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "`"}
"""Refused because the tool runs one git command with no shell: these tokens
would otherwise reach git as literal arguments and produce a confusing error."""

_REPO_RETARGETING = ("-C", "--git-dir", "--work-tree")
"""git options that point the command at a repository other than `env.work`."""

SYSTEM_PROMPT = """\
You are a git maintenance agent working in a single disposable repository. You
complete the user's request by running git commands and reading their output.

You have two tools. `run_git` runs one git command in the repository's working
directory; there is no file-reader, no shell, and no other way to act. Call it
with one command per turn. The command must start with `git`; shell operators
(&&, |, ;, redirects) and options that retarget the repository are refused.
`finish` declares that the request is satisfied and ends the task.

After each command you receive its exit code, stdout and stderr. Read failures
and correct them. Preserve anything the user told you must survive. As soon as
the request is satisfied, call `finish` with a one-line summary of what you did;
do not keep re-checking a repository that is already right."""


def solve(
    signature: TaskSignature,
    env: Sandbox,
    provider: Provider,
    *,
    max_steps: int = 12,
    prelude: str | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> tuple[EpisodeOutcome, list[dict]]:
    """Run the arm-1 loop and return its outcome with the full transcript.

    The loop sends the system prompt and the task text, lets the model call the
    one tool, feeds each result back, and repeats. It ends when the model
    declares the task finished, after `max_steps` model turns, or once
    `max_tool_calls` tool calls have run (issue #160), whichever comes first.

    **The stopping rule must not consult the fault's checker.** A ground-truth
    oracle here would give arm 1 information the compiled arms are never given:
    they execute a body once and are graded afterwards, with no opportunity to
    loop until the environment passes. Stopping on the model's own declaration
    keeps the mechanism identical to a hand-run ReAct agent, and keeps the
    measurement attributable to the agent rather than to the oracle. Do not
    replace the model-declaration-driven termination with `fault.check(env).ok`;
    the caller grades the result with that checker after this function returns.

    Outcome mapping. `SUCCESS` means the model declared the task finished; it is
    **not** an assertion that the environment is correct. `solve` does not grade
    its own work and must not: the caller runs the fault's checker over the
    returned environment and records `ground_truth_ok`. An episode with
    `outcome=SUCCESS` and `ground_truth_ok=False` is therefore legal and
    expected -- it is the "wrong program fired and the episode still succeeded"
    quadrant the ledger exists to express. Exhausting the step budget or a
    provider error yields `FAIL`, with the reason left in the transcript.
    `FALLBACK` is the compiled arms' outcome, meaning "no stored program applies,
    so the agent takes over" (spec §8); arm 1 *is* that agent, so it never
    returns it.

    `prelude` is text placed before the task in the user message, and it is arm 1b's
    only difference from arm 1 (issue #7, ADR-0017): the recalled memory entries. It
    goes in the user message rather than the system prompt so the system prefix stays
    the one every arm sends. `None` -- arm 1 -- leaves the user message the task text
    alone, exactly as before.

    The transcript is a first-class output, not a debugging aid: the compile
    step reads it to author a program, so it records the system prompt, the task
    text, every model turn (with the tool calls it returned, in the API's own
    shape), and every tool result, in order.
    """
    task_text = signature.intent
    user_content = task_text if prelude is None else f"{prelude}\n\n{task_text}"
    transcript: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    tools = available_tools()
    executed = 0
    nudged = False

    for step in range(max_steps):
        last_turn = step == max_steps - 1
        nearly_out = max_tool_calls - executed <= NUDGE_TOOL_CALL_MARGIN
        if not nudged and step > 0 and (last_turn or nearly_out):
            # Once, before the turn that may be the last (issue #171). Budget only --
            # it never tells the agent whether the repository is right.
            transcript.append({"role": "user", "content": BUDGET_NUDGE, "nudge": True})
            nudged = True
        try:
            completion = provider.complete(
                system=SYSTEM_PROMPT, messages=_api_messages(transcript), tools=tools
            )
        except Exception as exc:  # provider errors are recorded, never swallowed
            transcript.append(
                {"role": "error", "content": f"provider error: {type(exc).__name__}: {exc}"}
            )
            return EpisodeOutcome.FAIL, transcript

        if not completion.tool_calls:
            # No call is the model's declaration that it is finished. It says
            # nothing about correctness; the caller grades that separately.
            transcript.append({"role": "assistant", "content": completion.text, "done": True})
            return EpisodeOutcome.SUCCESS, transcript

        transcript.append(
            {
                "role": "assistant",
                "content": completion.text,
                "tool_calls": completion.tool_calls,
            }
        )
        for call in completion.tool_calls:
            name, command = _parse_tool_call(call)
            if name == FINISH_TOOL:
                # The agent's own declaration (issue #171). Calls after it in the same
                # turn are not run: the agent has said it is done.
                transcript.append(
                    {"role": "assistant", "content": _finish_summary(call), "done": True}
                )
                return EpisodeOutcome.SUCCESS, transcript
            if executed >= max_tool_calls:
                # The budget counts commands, not turns: a model that batches calls
                # reaches it as surely as one that does not (issue #160). The call is
                # answered, not run, so the transcript stays a valid conversation for
                # the last word (issue #179), and it is not counted as a command.
                transcript.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": name,
                        "command": command,
                        "content": _refused("the tool-call budget is spent; not run"),
                        "ok": False,
                        "not_run": True,
                    }
                )
                continue
            executed += 1
            if name == "run_git":
                result, ok = _run_tool(command, env)
            else:
                result, ok = (
                    _refused(f"unknown tool {name!r}; the tools are 'run_git' and 'finish'"),
                    False,
                )
            transcript.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "command": command,
                    "content": result,
                    "ok": ok,
                }
            )
        if executed >= max_tool_calls:
            # No further turn could run a command, so the agent gets its last word now.
            return _last_word(
                transcript,
                provider,
                f"tool-call budget of {max_tool_calls} spent without a finish declaration",
            )

    return _last_word(
        transcript, provider, f"step budget of {max_steps} turns spent without a finish declaration"
    )


def _last_word(
    transcript: list[dict], provider: Provider, spent: str
) -> tuple[EpisodeOutcome, list[dict]]:
    """One more turn once a budget is spent, with only `finish` on offer (issue #179).

    `SUCCESS` only when the agent calls `finish`. A plain reply, a call to anything else,
    or a provider error is `FAIL`, recorded with which budget ran out.
    """
    transcript.append({"role": "user", "content": LAST_WORD, "last_word": True})
    try:
        completion = provider.complete(
            system=SYSTEM_PROMPT, messages=_api_messages(transcript), tools=[_finish_tool()]
        )
    except Exception as exc:  # provider errors are recorded, never swallowed
        transcript.append(
            {"role": "error", "content": f"provider error: {type(exc).__name__}: {exc}"}
        )
        transcript.append({"role": "error", "content": spent})
        return EpisodeOutcome.FAIL, transcript
    for call in completion.tool_calls or []:
        name, _ = _parse_tool_call(call)
        if name == FINISH_TOOL:
            transcript.append(
                {
                    "role": "assistant",
                    "content": _finish_summary(call),
                    "done": True,
                    "last_word": True,
                }
            )
            return EpisodeOutcome.SUCCESS, transcript
    transcript.append({"role": "assistant", "content": completion.text, "last_word": True})
    transcript.append(
        {"role": "error", "content": f"{spent}; the last word did not declare the task done"}
    )
    return EpisodeOutcome.FAIL, transcript


def available_tools() -> list[dict]:
    """The one tool every arm gets, in the OpenAI/DeepSeek function-calling shape.

    Identical across arms so the tool surface cannot explain a difference
    between them. The schema is sent to the provider and the loop reads back the
    structured `tool_calls` the provider surfaces on `Completion`; there is no
    text protocol to fall back to, because one path is the API's own.

    What contains the tool's risk
    -----------------------------
    The **sandbox** is the containment: `env.work` is a disposable clone built
    by `sandbox.create`, destroyed after the episode, and never a real fork. The
    checks in `_run_tool` -- argv[0] must be `git`, no shell operators, no
    option that retargets the repository -- keep the command pointed at that
    clone; they are not a security boundary against a determined model, because
    a git command can still damage the sandbox. Damaging the sandbox is the
    accepted cost; damaging the host is not, and running without a shell is what
    makes `rm -rf ...` a refusal rather than an execution.

    This is deliberately **not** `runtime.guard`. The guard constrains a
    replayed program body that runs unattended and may contain arbitrary shell;
    it is stricter than this and is issue #10's territory. Nothing here
    implements it.
    """
    tools: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": "run_git",
                "description": (
                    "Run one git command in the sandbox working directory and return its "
                    "exit code, stdout and stderr. The command must start with 'git'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "One git command line, e.g. 'git status --porcelain'.",
                        }
                    },
                    "required": ["command"],
                },
            },
        },
        _finish_tool(),
    ]
    return tools


def _finish_tool() -> dict:
    """The `finish` declaration's schema, offered every turn and alone on the last word."""
    return {
        "type": "function",
        "function": {
            "name": FINISH_TOOL,
            "description": (
                "Declare that the user's request is satisfied and end the task. Call it "
                "as soon as the repository is in the requested state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One line saying what was done.",
                    }
                },
                "required": ["summary"],
            },
        },
    }


def _run_tool(command: str, env: Sandbox) -> tuple[str, bool]:
    """Run one model-supplied command; return (result text, ok).

    Refusals and git failures are returned as text rather than raised, so the
    model can read them and correct itself in the next turn. See
    `available_tools` for what this guard is and is not.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _refused(f"could not parse command {command!r}: {exc}"), False
    if not argv:
        return _refused("empty command"), False
    if argv[0] != "git":
        return _refused(f"only git commands are allowed, got {argv[0]!r}"), False
    if any(token in _SHELL_OPERATORS for token in argv[1:]):
        return _refused("one git command per call; shell operators are not run"), False
    retargeting = [token for token in argv[1:] if token.startswith(_REPO_RETARGETING)]
    if retargeting:
        return (
            _refused(f"{retargeting[0]!r} would run outside the sandbox working directory"),
            False,
        )
    overrides = disallowed_git_config_overrides(argv)
    if overrides:
        # Command-line config wins over the hardened environment, so an override
        # could re-enable hooks or other command-running config (issue #159).
        return (
            _refused(
                f"config override {overrides[0]!r} is not allowed; only "
                f"{sorted(ALLOWED_GIT_CONFIG_OVERRIDES)} may be set with -c"
            ),
            False,
        )

    if env.checkout is not None:
        return _run_on_checkout(command, argv[1:], env)
    try:
        result = run_git(argv[1:], cwd=env.work, check=False, timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"timed out after {_GIT_TIMEOUT_S:.0f}s", False
    return _format_output(result), result.returncode == 0


def _run_on_checkout(command: str, args: list[str], env: Sandbox) -> tuple[str, bool]:
    """One tool call on an existing checkout: screened, `run_env`, confined.

    On a checkout (#181) the remote is real and on the network, and the agent's commands
    are model-authored like any body, so they run the way every model-authored command on
    a checkout runs. They pass `runtime.guard.screen`, the screen bodies pass, which
    refuses an explicit URL or `git@host:` target, a credential path, a write outside the
    checkout and a force-push -- on a host with no network namespace that screen is what
    stops `git push https://...` from carrying the user's code away. They run under
    `sandbox.run_env`, so the remote's URL reads the trusted pre-fetch's mirror and a
    commit carries the user's identity, and through `runtime.confine.run_confined`, so
    there is no network where the host allows that. A harness sandbox keeps the direct,
    unscreened `run_git` its measurements ran under: its remote is a local path, and it
    holds nothing to take.
    """
    decision = screen(command, env_root=str(env.work))
    if decision.verdict is Verdict.REFUSE:
        return _refused(f"guard {decision.reason}"), False
    confined = run_confined(
        ["git", *args], cwd=env.work, env=run_env(env), timeout_s=_GIT_TIMEOUT_S
    )
    if confined.timed_out or confined.returncode is None:
        return f"timed out after {_GIT_TIMEOUT_S:.0f}s", False
    result = subprocess.CompletedProcess(
        ["git", *args], confined.returncode, confined.stdout, confined.stderr
    )
    return _format_output(result), confined.returncode == 0


def _refused(reason: str) -> str:
    return f"refused: {reason}"


def _format_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = [f"exit code: {result.returncode}"]
    if result.stdout.strip():
        parts.append(f"stdout:\n{_truncate(result.stdout)}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{_truncate(result.stderr)}")
    return "\n".join(parts)


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n[truncated; {len(text)} characters total]"


def _api_messages(transcript: list[dict]) -> list[dict]:
    """Map the transcript onto the message roles the provider protocol accepts.

    The system prompt is passed separately and errors are terminal, so both are
    dropped here. An assistant turn keeps its `tool_calls` exactly as the API
    returned them, and each result is answered with the `role: "tool"` message
    the function-calling protocol requires, keyed by `tool_call_id`. Sending a
    result as a `user` message -- what a text protocol would do -- leaves the
    assistant turn's call unanswered, which the API rejects.
    """
    messages: list[dict] = []
    for entry in transcript:
        role = entry["role"]
        if role in ("system", "error"):
            continue
        if role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": entry.get("tool_call_id"),
                    "content": entry["content"],
                }
            )
        elif role == "assistant" and entry.get("tool_calls"):
            messages.append(
                {
                    "role": "assistant",
                    "content": entry["content"],
                    "tool_calls": entry["tool_calls"],
                }
            )
        else:
            messages.append({"role": role, "content": entry["content"]})
    return messages


def _finish_summary(call: dict) -> str:
    """The `summary` a `finish` call carried, or `""` when it is missing or malformed."""
    function = call.get("function")
    raw = function.get("arguments") if isinstance(function, dict) else None
    try:
        arguments = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return ""
    summary = arguments.get("summary") if isinstance(arguments, dict) else None
    return summary if isinstance(summary, str) else ""


def _parse_tool_call(call: dict) -> tuple[str, str]:
    """The (name, command) of one API tool call, never raising.

    `arguments` arrives as a JSON string in the API's shape and is decoded here.
    A call whose `function` is malformed, whose name is not `run_git`, or whose
    arguments do not decode to a `command` string yields a value the loop can
    refuse as a tool result, so one bad call does not end the episode.
    """
    function = call.get("function")
    if not isinstance(function, dict):
        return "", ""
    name = function.get("name")
    command = ""
    raw = function.get("arguments")
    if isinstance(raw, str) and raw:
        try:
            arguments = json.loads(raw)
        except ValueError:
            arguments = None
        if isinstance(arguments, dict) and isinstance(arguments.get("command"), str):
            command = arguments["command"]
    return name if isinstance(name, str) else "", command
