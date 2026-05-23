"""Command-line interface for reproducible runs."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from helpers.validate_config import validate_config_file
from pydantic import ValidationError
import yaml

from runner import run_experiment


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description='Run experiments with full observability',
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	parser.add_argument(
		'--config',
		type=Path,
		required=True,
		help='Path to experiment configuration file (YAML)',
	)
	parser.add_argument(
		'--output-dir',
		type=Path,
		default=Path('data/experiments/geopolitical/kimi'),
		help='Directory to write logs and summaries',
	)
	parser.add_argument(
		'--verbose',
		'-v',
		action='store_true',
		help='Enable debug logging (verbose output)',
	)
	return parser.parse_args()


def main() -> None:
	args = _parse_args()

	try:
		validated_config = validate_config_file(args.config)

		start_time = time.monotonic()

		run_experiment(
			config_path=str(args.config),
			config_data=validated_config.model_dump(by_alias=True),
			output_dir=str(args.output_dir),
			verbose=args.verbose,
		)

		total_time = time.monotonic() - start_time
		print(f'Total experiment time: {total_time:.2f}s')

	except (ValidationError, yaml.YAMLError, ValueError, OSError) as e:
		print(f'Config validation failed: {e}', file=sys.stderr)
		sys.exit(2)

	except KeyboardInterrupt:
		print('\n\nExperiment interrupted by user', file=sys.stderr)
		sys.exit(130)

	except Exception as e:
		print(f'\nError: {e}', file=sys.stderr)
		sys.exit(1)


if __name__ == '__main__':
	main()
