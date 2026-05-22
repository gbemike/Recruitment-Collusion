import pytest
from helpers.validate_config import validate_config_file
from schema import ConfigPath


def test_validate_config(valid_config_data):
	validated = validate_config_file(valid_config_data)

	assert validated is not None
	assert isinstance(validated, ConfigPath)
