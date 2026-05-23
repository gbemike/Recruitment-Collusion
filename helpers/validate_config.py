"""Configuration file validation."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from schema import ConfigPath


def validate_config_file(config_path: Path) -> ConfigPath:
	"""Validate and load configuration from a YAML file."""
	config_path = Path(config_path)
	if config_path.suffix in ['.yaml', '.yml']:
		if yaml is None:
			raise RuntimeError(
				'PyYAML required for .yaml files. Install with `pip install pyyaml`.'
			)
		with open(config_path, 'r') as f:
			try:
				data = yaml.safe_load(f)
			except yaml.YAMLError:
				logging.exception(f'Invalid YAML in {config_path}')
				raise

		# validate fields within yaml
		validated = ConfigPath.model_validate(data)
		return validated

	raise ValueError(f'Config must be a YAML file (.yaml or .yml): {config_path}')
