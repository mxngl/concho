"""``python -m engines.schedule <step> ...`` (same as ``concho-schedule``)."""

import sys

from engines.schedule.cli import main

sys.exit(main())
