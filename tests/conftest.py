import yaml
import pytest
from pathlib import Path


@pytest.fixture
def valid_config_data():
	path = Path(
		'/home/gbemike/Documents/github/Recruitment-Collusion/tests/testdata/valid_config.yaml'
	)
	return path
