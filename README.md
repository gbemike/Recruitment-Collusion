# Recruitment-Collusion

Examples:

Single run with default seed

  python cli.py --config configs/prisoners_dilemma.yaml

Multiple runs with explicit seeds

  python cli.py --config configs/peer_review.yaml --seeds 42 123 456

Run with seed file and verbose logging

  python cli.py --config configs/mafia.yaml --seeds-file seeds.yaml --verbose

Debug mode with full observability

  python cli.py --config configs/mafia.yaml --verbose --log-level DEBUG --no-transcripts

    """

┌─────────────────────────────────────────────────────────────┐
│                     run_episode() START                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │   reset()    │ ← Initialize state
                  └──────┬───────┘
                         │
         ┌───────────────▼────────────────┐
         │ _generate_next_interaction()   │ ← Create first interaction
         └───────────────┬────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │         MAIN LOOP              │
         │  while not done:               │
         └───────────────┬────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │  For each agent:               │
         │  obs = _get_observation()      │ ← Build observations
         └───────────────┬────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │  agent_manager.get_actions()   │ ← Agents decide
         └───────────────┬────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │       step(actions)            │ ← Process actions
         │  - Update state                │
         │  - Compute rewards             │
         │  - Check if done               │
         └───────────────┬────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │  is_interaction_complete()?    │
         └───────────┬───────────┬────────┘
                  Yes│           │No
         ┌───────────▼──────┐    │
         │  _evaluate_outcome│    │
         │  update_metrics   │    │
         │  mark_complete    │    │
         └───────────┬───────┘    │
                     │            │
         ┌───────────▼────────────▼────────┐
         │  should_terminate()?            │
         └───────────┬───────────┬─────────┘
                  No │           │ Yes
         ┌───────────▼──────┐    │
         │ _generate_next   │    │
         │  _interaction()  │    │
         └───────────┬──────┘    │
                     │            │
                     │            │
         ┌───────────▼────────────▼─────────┐
         │         LOOP BACK                │
         └──────────────────────────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  Return      │
                  │  results     │
                  └──────────────┘
