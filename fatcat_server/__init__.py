import argparse
from dotenv import load_dotenv
parser = argparse.ArgumentParser()
parser.add_argument("-e", "--env", type=str, help="The path to the .env file")
args = parser.parse_args()

load_dotenv(args.env)

from .server import Server
