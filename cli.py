"""Command-line interface for ColludeBench reproducibility runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runner import run_experiment, run_from_config, run_with_seed_file


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
        "--seeds",
        type=int,
        nargs="*",
        default=None,
        help="Explicit list of seeds to use (overrides config)",
    )
    parser.add_argument(
        "--seeds-file",
        type=Path,
        help="Optional YAML file mapping scenario names to seed lists",
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
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress all output except errors",
    )
    
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    
    if args.quiet:
        args.log_level = "ERROR"
        args.verbose = False
    
    try:
        if args.seeds_file is not None:
            summary = run_with_seed_file(
                args.config,
                args.seeds_file,
                output_dir=args.output_dir,
                scenario=args.scenario,
                write_transcripts=not args.no_transcripts,
                verbose=args.verbose,
                log_level=args.log_level
            )
        elif args.seeds is not None:
            summary = run_from_config(
                args.config,
                seeds=args.seeds,
                output_dir=args.output_dir,
                write_transcripts=not args.no_transcripts,
                verbose=args.verbose,
                log_level=args.log_level
            )
        else:
            results = run_experiment(
                config_path=str(args.config),
                output_dir=str(args.output_dir),
                write_transcript=not args.no_transcripts,
                verbose=args.verbose,
                log_level=args.log_level
            )
            return
        
        if not args.quiet:
            aggregate = summary.get("aggregate", {})
            print("\n" + "="*60)
            print("AGGREGATE SUMMARY")
            print("="*60)
            print(json.dumps(aggregate, indent=2))
            print("="*60)
    
    except KeyboardInterrupt:
        print("\n\nExperiment interrupted by user", file=sys.stderr)
        sys.exit(130)
    
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        if args.log_level == "DEBUG":
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()