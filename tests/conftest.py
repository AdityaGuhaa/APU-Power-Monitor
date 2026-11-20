"""Make the project root importable regardless of how the tests are invoked."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
