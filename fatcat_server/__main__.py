import os
import socket
from fatcat_utils import FatCat
from .__init__ import Server


def main():
    fatcat = FatCat(f"{os.getenv('FATCAT_LOGGER_NAME', socket.gethostname())}")
    server = Server(fatcat)
    fatcat.add_listener_group(server)
    fatcat.run()


if __name__ == "__main__":
    main()
