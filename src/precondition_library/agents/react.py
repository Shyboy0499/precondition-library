"""Arm 1: the ReAct baseline. No library, full LLM cost per episode.

This arm is the honest yardstick the other two are measured against, so it must
be given every advantage a reasonable engineer would give it by hand: a good
system prompt, the same tool surface the compiled programs get, and the same
sandbox. A deliberately crippled baseline would make the other arms look better
and the result worthless.

The stopping rule is the part a later reader is most likely to "simplify" back
into a defect, so it is stated on `solve` as well as here: the loop stops when
the model declares the task finished, or when `max_steps` runs out. It must
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
from ..sandbox import Sandbox, run_git
from ..signatures import TaskSignature

_GIT_TIMEOUT_S = 30.0
"""Wall-clock bound on one tool call. A git command in a local sandbox is
instant; anything slower is a hang, and hanging unattended is a failure mode."""

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

You have exactly one tool, `run_git`, which runs one git command in the
repository's working directory. There is no file-reader, no shell, and no other
tool. Call it with one command per turn. The command must start with `git`;
shell operators (&&, |, ;, redirects) and options that retarget the repository
are refused.

After each command you receive its exit code, stdout and stderr. Read failures
and correct them. Preserve anything the user told you must survive, and do not
stop until you believe the request is satisfied. When you are finished, reply
with your final answer and no tool call."""


def solve(
    signature: TaskSignature,
    env: Sandbox,
    provider: Provider,
    *,
    max_steps: int = 12,
) -> tuple[EpisodeOutcome, list[dict]]:
    """Run the arm-1 loop and return its outcome with the full transcript.

    The loop sends the system prompt and the task text, lets the model call the
    one tool, feeds each result back, and repeats. It ends when the model
    declares the task finished or after `max_steps` model turns, whichever comes
    first.

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

    The transcript is a first-class output, not a debugging aid: the compile
    step reads it to author a program, so it records the system prompt, the task
    text, every model turn (with the tool calls it returned, in the API's own
    shape), and every tool result, in order.
    """
    task_text = signature.intent
    transcript: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_text},
    ]
    tools = available_tools()

    for _ in range(max_steps):
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
            if name == "run_git":
                result, ok = _run_tool(command, env)
            else:
                result, ok = _refused(f"unknown tool {name!r}; only 'run_git' exists"), False
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

    transcript.append(
        {
            "role": "error",
            "content": (
                f"step budget exhausted after {max_steps} steps without a finish declaration"
            ),
        }
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
        }
    ]
    return tools


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

    try:
        result = run_git(argv[1:], cwd=env.work, check=False, timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"timed out after {_GIT_TIMEOUT_S:.0f}s", False
    return _format_output(result), result.returncode == 0


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
