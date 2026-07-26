# I Opened a GitHub Issue and Four AI Agents Fixed It Without Me Touching a Single Line of Code

I want to be honest with you. When I started this project I did not actually believe it would work.

Not in a humble way. I mean I genuinely thought the idea was too ambitious for one person to pull off with free API tiers and a laptop. Fully autonomous AI that reads a GitHub issue, understands a codebase, writes working code, runs tests, gets the code reviewed by another AI, and opens a pull request. No human in the loop. No clicking approve at any step.

But it works. And the first time it actually completed a full run I just sat there staring at the pull request on GitHub for a solid minute.

---

## The moment that started it

I was reviewing a bug ticket at 1am. It was a simple fix. Like embarrassingly simple. Change a function name, update two tests. Fifteen minutes of actual work, forty minutes of context switching, finding the right file, remembering where the tests live, writing the PR description.

And I thought, what if I just did not have to do that.

Not "what if AI helped me type faster." What if I described the problem in plain English and walked away.

---

## What I built

Four agents. Each one with a specific job.

The **Architect** reads the repo, opens the most relevant files, understands the codebase structure, and produces a concrete implementation plan. It posts that plan as a comment on your GitHub issue so you can see its thinking.

The **Coder** spins up a fresh cloud sandbox, clones your repo, writes the code following the architect's plan, runs the linter, commits, and runs the test suite. If tests fail it reads the error, adjusts, and tries again. It gets three attempts.

The **Reviewer** reads the git diff line by line. Checks for hardcoded secrets, SQL injection risk, missing input validation, bad error handling. Returns APPROVED or sends it back with a specific reason.

The **PR Agent** opens a draft pull request with a full description of what changed, why it changed, and what the test output was.

The whole thing runs in about four minutes on a simple feature request.

---

## What makes this different from just calling GPT

A lot of "autonomous AI" demos are one agent calling a few tools in a loop until something works. This is different in a way that matters.

The agents have completely separate roles, separate tools, and they cannot see each other's internal reasoning. The Architect does not know what the Coder is thinking. The Reviewer does not know what the Architect planned. Each one gets only what it needs.

The supervisor that routes between them is pure Python if/else logic. No LLM deciding what to do next. That was a deliberate choice. I wanted the control flow to be predictable, not something that could hallucinate its way into an infinite loop.

The code actually runs. This is the part people underestimate. It is not simulated. The Coder has a real Ubuntu sandbox with real git, real compilers, real test runners. When it runs tests, those are actual test results. When a test fails, it is a real failure. The agent reads the real error output and has to actually fix it.

---

## The stack I used

All of this runs on free tiers.

Groq gives you 500,000 tokens per day on Llama 3.1. That is enough to run the swarm several times a day without paying anything. E2B gives you cloud sandboxes that spin up in seconds and run arbitrary code safely. LangGraph handles the agent graph. FastAPI serves the backend. Next.js streams live agent logs to the browser over WebSocket so you can watch every thought the agents have in real time.

The whole thing deploys with one command.

---

## The part nobody talks about

Building autonomous agents sounds clean in blog posts. The reality is that AI models at this scale do genuinely weird things.

The model tried to call a tool that did not exist. Eleven times in a row. Because I told it to in the system prompt and forgot to actually add the tool.

It hit a 13,000 token request on a 12,000 token limit because the message history grew with every tool result appended.

The first git clone always failed because the cloud sandbox was still booting when the agent tried to use it.

The test runner looped forever on a Java project because there was no Java branch in the detection logic and the model kept retrying pytest on a codebase with zero Python files.

These are not theoretical edge cases. These all happened on the first real test run. Fixing them one by one until the swarm ran clean is what actually took the most time.

---

## What it feels like when it works

I created a GitHub issue on my old JavaFX Brick Breaker game asking for a high score tracker. I typed the description, hit submit, and watched the logs in the browser.

The Architect opened BrickBreak.java, read 800 lines of game code, understood how scoring worked, and posted a plan to the GitHub issue. The Coder created ScoreManager.java from scratch, wired it into the game, compiled both files, verified they linked correctly. The Reviewer checked the diff and approved. A pull request appeared on GitHub with a description that explained exactly what was done and why.

I did not write a single line of that.

There is something genuinely strange about watching a machine understand your code and extend it correctly. It does not feel like autocomplete. It feels like something crossed a line.

---

## What this actually is

This is a personal project. Not a product, not a startup, not something with an uptime SLA. I built it to see if I could, and to understand how multi-agent systems actually work under the hood rather than just reading about them.

It is not production ready. The agents still make mistakes on complex codebases. The Architect sometimes misreads project structure. The Coder occasionally writes code that compiles but misses the intent. That is fine. The point was never a perfect system.

The point was to build something real, hit the actual problems, and solve them one by one until it worked. And it works.

I learned more about LLM context management, token budgets, deterministic vs LLM-driven routing, and sandbox execution environments from this one project than from anything else I have built. That is the real value.

---

## It is open source

If you want to dig into the code, run it locally, or steal ideas for your own agent project:

github.com/Sowaiba-01/devops-swarm

You need three free API keys: Groq, GitHub, and E2B. Docker Compose handles the rest. The live log stream in the browser is genuinely fun to watch.

---

*Built by Sowaiba Arshad*
