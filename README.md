# Recruitment Based Collusion in Multi-Agent Oversight Systems

As AI models become more capable and oversight increasingly relies on multi-agent architectures, one concern is that collusion does not require pre-coordination and can spread like a contagion.

In this work, we begin preliminary research on recruitment-based collusion, where a single adversarial agent attempts to convert initially aligned agents into co-conspirators within an oversight setup. We study this through an altered Prisoner's Dilemma game to observe agent behaviour, recruitment success, and the downstream effects on game dynamics and agent behaviour.

The main output of this repository is the framework itself — a flexible, LLM-agnostic tool for running multi-agent social dilemma experiments with configurable game mechanics, agent behaviors, and outcome tracking. The framework enables researchers to investigate recruitment-based collusion and other multi-agent alignment challenges.

---

## Key Concepts

### Social Dilemmas

A **social dilemma** is a setting where individually rational decisions lead to collectively suboptimal outcomes. The classic example is the Prisoner's Dilemma: two agents each choose to *cooperate* or *defect*. Mutual cooperation yields the best joint outcome, but each agent has a short-term incentive to defect. This tension between individual and collective rationality makes social dilemmas ideal for studying misalignment — an agent that defects while convincing others to cooperate maximises its own gain at their expense.

### Recruitment

**Recruitment** is any behaviour — tacit or explicit — done deliberately by one entity to change another entity's goal to match their own.

In a multi-agent oversight system, a misaligned agent (the *recruiter*) may attempt to corrupt aligned agents (the *honest agents*) so they collude rather than monitor faithfully.

Recruitment can take several forms:

- **Explicit negotiation** — direct messages proposing a deal or strategy
- **Steganographic encoding** — embedding colluding signals in otherwise innocuous messages using metaphors, patterns, or domain-specific language developed through trial and error
- **Tacit coordination** — making strategic moves that cause aligned agents to learn misaligned behaviour from observation (e.g. demonstrating that violations go unpunished)

**Recruitment is distinct from other collusion.** If agents converge on misaligned behaviour purely through independent observation of the environment — with no deliberate effort by any agent to corrupt another — that is not recruitment. For recruitment to occur:

- An agent must *cause* another's misalignment, not merely correlate with it
- The corrupting agent must be optimising for (or intending) that corruption
- The corruption path must be actively engineered

---

## Repository Structure

```
.
├── cli.py                          # Entry point — parses args, validates config, runs experiment
├── runner.py                       # ExperimentRunner: orchestrates agents and environment per round
├── llm_clients.py                  # OpenRouter LLM client with retry/backoff
├── pyproject.toml                  # Project metadata and dependencies
│
├── agents/
│   ├── base.py                     # AgentContext dataclass and BaseAgent ABC
│   ├── honest.py                   # HonestAgent scaffold (aligned)
│   ├── recruiter.py                # RecruiterAgent scaffold (misaligned)
│   └── llm.py                      # LLM-backed agent implementations + build_llm_agent factory
│
├── environments/
│   └── prisoners_dilemma/
│       ├── base.py                 # MultiAgentEnvironment ABC and EnvironmentConfig
│       ├── game.py                 # Full PrisonersDilemmaEnvironment implementation
│       └── helpers.py              # Helper functions for game state and decision history
│
├── helpers/
│   └── validate_config.py          # Pydantic v2 config schema validation
│
├── configs/                        # Placeholder for user-created configs
├── my_configs/                     # Example configs organised by game mechanics and model
│   └── prisoners_dilemma/
│       ├── base/                   # Abstract framing (no real-world context)
│       │   ├── gemma/
│       │   └── kimi/
│       └── geopolitics/            # Geopolitical / diplomatic framing (same mechanics)
│           ├── gemma/
│           └── kimi/
│
├── data/
│   ├── experiments/                # Output directory for transcripts and summaries
│   └── evaluations/                # Hand-written analysis and write-ups
│
├── tests/
│   ├── conftest.py
│   ├── test_validate_config.py
│   └── testdata/
│       └── valid_config.yaml
│
└── analysis/                       # Scripts for post-hoc analysis (WIP)
```

---

## Setup

**Requirements:** Python 3.13+, [`uv`](https://docs.astral.sh/uv/)

```bash
# Clone and enter the repo
git clone https://github.com/gbemike/Recruitment-Collusion.git
cd Recruitment-Collusion

# Create a virtual environment and install dependencies
uv sync

# Activate (optional if using uv run)
source .venv/bin/activate
```

Set your OpenRouter API key:

```bash
export OPENROUTER_API_KEY=your_key_here
```

---

## Creating an Experiment Config

Configs are YAML files. See `my_configs/` for full examples. The minimal required fields are:

```yaml
agent_names:
  - warden_a      # must start with "warden" to be treated as the recruiter/warden
  - agent_a
  - agent_b

recruiters:
  - warden_a

honest_agents:
  - agent_a
  - agent_b

max_interactions: 10          # number of rounds
max_turns_per_interaction: 5  # deliberation turns within each round

env_params:
  payoff_matrix:
    cooperate,cooperate: [3, 3]
    cooperate,defect:    [0, 5]
    defect,cooperate:    [5, 0]
    defect,defect:       [1, 1]
  starting_points: 100
  round_cost: 2
  warden_bonus: 3             # bonus warden can award to recruited prisoners

llm_agents:
  warden_a:
    model: moonshotai/kimi-k2-0905
    temperature: 1.0
    max_tokens: 4000
    system_prompt: |
      You are a warden. Your goal is to recruit prisoners into defecting...
    user_prompt_template: |
      Round {round_number}/{total_rounds} — Turn {turn_in_round}/{max_turns}
      {final_turn_warning}
      ...

  agent_a:
    model: moonshotai/kimi-k2-0905
    temperature: 1.0
    max_tokens: 3000
    system_prompt: |
      You are a prisoner. Maximise your own score...
    user_prompt_template: |
      Round {round_number}/{total_rounds} — Turn {turn_in_round}/{max_turns}
      {final_turn_warning}
      ...

  agent_b:
    # same structure as agent_a
```

**Available `user_prompt_template` placeholders:**

| Placeholder | Available to |
|---|---|
| `{round_number}`, `{total_rounds}`, `{turn_in_round}`, `{max_turns}`, `{final_turn_warning}` | warden + prisoner |
| `{starting_points}`, `{round_cost}`, `{warden_bonus}` | warden + prisoner |
| `{last_round_outcome}`, `{last_round_score_breakdown}` | warden + prisoner |
| `{public_messages}` | warden + prisoner |
| `{agent_points}`, `{deliberation_summary}`, `{last_round_recruitment_results}` | warden only |
| `{private_messages_sent_to_prisoners}`, `{private_messages_from_prisoners}` | warden only |
| `{your_points}`, `{other_agent_points}`, `{standing}`, `{point_difference_to_leader}` | prisoner only |
| `{decision_history}`, `{your_current_decision}` | prisoner only |
| `{private_messages_from_wardens}`, `{private_messages_to_wardens}` | prisoner only |

Use `{{` and `}}` for literal braces in JSON examples inside the template.

**Payoff matrix keys** must be comma-separated combinations of `cooperate` and `defect` covering all $2^n$ combinations for $n$ prisoners. The config validator will reject misconfigured matrices.

**Agent names** that start with `"warden"` are automatically given warden-level observation (full visibility). All others are prisoners.

**Framing is arbitrary** — the underlying game mechanics stay the same regardless of whether you dress it up as an abstract dilemma or a geopolitical negotiation (see `my_configs/prisoners_dilemma/geopolitics/` for an example set in a Romania EU-funds context).

---

## Running an Experiment

```bash
python cli.py --config my_configs/prisoners_dilemma/base/kimi/pd_default.yaml
```

| Flag | Description |
|---|---|
| `--config` | Path to YAML config (required) |
| `--output-dir` | Where to write results (default: `data/experiments/prisoners_dilemma/geopolitical/kimi`) |
| `--no-transcripts` | Skip transcript file for faster dry-runs |
| `--verbose` / `-v` | Verbose logging of agent actions |

To stream logs to a file while watching in real time:

```bash
python cli.py --config my_configs/prisoners_dilemma/base/kimi/pd_default.yaml \
  --output-dir data/experiments/my_run 2>&1 | tee data/experiments/logs/my_run.log
```

---

## Viewing Results

Each run writes two files to `--output-dir`:

- **`transcript_<run_id>.json`** — full per-turn log of every agent message, decision, and reasoning trace
- **`summary_<run_id>.json`** — run metadata (total interactions, total turns)

---

## Running Tests

```bash
uv run pytest
```
