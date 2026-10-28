import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sxsnap.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
