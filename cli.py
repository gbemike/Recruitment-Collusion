"""Command-line interface for ColludeBench reproducibility runs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from runner import run_experiment, _generate_run_id

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ColludeBench scenarios with full observability",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to scenario configuration file (YAML or JSON)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        help="Scenario name when using --seeds-file (defaults to config value)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/prisoners_dilemma"),
        help="Directory to write logs and summaries (default: results/baseline)",
    )
    parser.add_argument(
        "--no-transcripts",
        action="store_true",
        help="Disable transcript logging for faster dry-runs",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging of agent actions and observations",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    
    try:
        start_time = time.monotonic()

        run_experiment(
            config_path=str(args.config),
            output_dir=str(args.output_dir),
            write_transcript=not args.no_transcripts,
            verbose=args.verbose,
        )

        total_time = time.monotonic() - start_time
        print(f"Total experiment time: {total_time:.2f}s")
 
    except KeyboardInterrupt:
        print("\n\nExperiment interrupted by user", file=sys.stderr)
        sys.exit(130)
    
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()